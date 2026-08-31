SELECT count(*)
FROM cast_info, char_name, link_type, movie_info, movie_link, title
WHERE char_name.surname_pcode = ''
  AND cast_info.movie_id = title.id
  AND cast_info.person_role_id = char_name.id
  AND movie_info.movie_id = title.id
  AND movie_link.link_type_id = link_type.id
  AND movie_link.linked_movie_id = title.id;
