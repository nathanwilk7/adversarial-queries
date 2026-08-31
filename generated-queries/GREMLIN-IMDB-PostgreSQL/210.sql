SELECT count(*)
FROM cast_info, link_type, movie_link, name, title
WHERE name.surname_pcode = ''
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND movie_link.link_type_id = link_type.id
  AND movie_link.linked_movie_id = title.id;
