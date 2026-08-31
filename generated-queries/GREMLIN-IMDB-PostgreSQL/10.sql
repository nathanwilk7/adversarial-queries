SELECT count(*)
FROM aka_name, cast_info, char_name, link_type, movie_link, name, title
WHERE char_name.surname_pcode = ''
  AND aka_name.person_id = name.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND cast_info.person_role_id = char_name.id
  AND movie_link.link_type_id = link_type.id
  AND movie_link.linked_movie_id = title.id;
