SELECT count(*)
FROM aka_title, info_type, link_type, movie_info, movie_link, name, person_info, title
WHERE aka_title.title = 'Anonima ricatti'
  AND aka_title.movie_id = title.id
  AND movie_info.info_type_id = info_type.id
  AND movie_info.movie_id = title.id
  AND movie_link.link_type_id = link_type.id
  AND movie_link.linked_movie_id = title.id
  AND person_info.info_type_id = info_type.id
  AND person_info.person_id = name.id;
